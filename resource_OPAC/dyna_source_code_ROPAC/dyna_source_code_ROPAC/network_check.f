      SUBROUTINE BacktrackPath(i,iz)
      use muc_mod

	integer i
	real labelc, oldlabelc
	
	integer foundflag, prevnode,prevprevnode

		foundflag =0
          ifrom=idnod(i)
          ito=iz

          ict = 1
		icu1 = i

            know=1
            k=1


         mov=ForToBackLink(i)-backpointr(ifrom)+1

	  labelc=0
	  oldlabelc =0

        do while(ifrom.ne.destination(ito).and.foundflag.eq.0)
             if(know.eq.0) then
               know=1
             endif

             ifromtmp=ifrom
             ktemp=know
             movetemp=mov
             icttemp=ict
         ict = 1

       labelc=LabelOut(1,1,ito,ifromtmp,icttemp,ktemp,movetemp)

	 if(labelc.ge.(INFINITY-1)) then
	write(911,*) "please check link ",nodenum(iunod(i)),
     + "-> ", nodenum(idnod(i)), " which might be isoloated" 
		exit   
		 endif



		if(k.eq.1) then
		oldlabelc = labelc
		prevnode = idnod(i)
		prevprevnode = iunod(i)
		endif

         mov=  pathpointerout3(1,1,ito,
     *                     ifromtmp,icttemp,ktemp,movetemp)
         know= pathpointerout2(1,1,ito,
     *                      ifromtmp,icttemp,ktemp,movetemp)
         ifrom=pathpointerout1(1,1,ito,
     *                      ifromtmp,icttemp,ktemp,movetemp)

	write(911,*) k, nodenum(ifromtmp), labelc,ifrom

      if(mov.lt.1.or.know.lt.1.or.ifrom.lt.1.or.
     +	(oldlabelc-labelc).ge.9999)then

!	write(911,*) k, nodenum(idnod(i)),iz,nodenum(prevnode),
!     + nodenum(ifromtmp), nodenum(ifrom),oldlabelc-labelc

	foundflag =1

	endif

	if(foundflag.eq.1) then
	write(911,*) "please check outgoing movements from link ",
     +	nodenum(prevprevnode),"-> ", nodenum(prevnode),
     +      "due to signal phasing or movement.dat"


	endif
	oldlabelc = labelc

	if(k.gt.2) then
	prevprevnode = prevnode
	prevnode = ifromtmp
	endif
	k = k+1
	enddo

	


	END SUBROUTINE


      subroutine network_check(iz)

      use muc_mod
      integer::pathtemp(1000) = 0
	integer iz, ito
	integer error



	real labelcost_origin
	integer mov	

c -- 
      do i = 1,noofarcs
c --  define destination and origin
c --  assign the pointer of the initial address
		if(link_iden(i)<99) then		

          ifrom=idnod(i)
          ito=iz
c  --
c  -- follow the shortest path code
c  --

           mov=ForToBackLink(i)-backpointr(ifrom)+1

c  --
c  -- follow the shortest path code
c  --	

          ict = 1
		icu1 = i

           know=1
           k=1

       labelcost_origin=LabelOut(1,1,ito,ifrom,1,1,mov)


	 if(labelcost_origin.gt.1000) then
		connectivity(i,ito) = 0 ! No connectivity
	 else
		connectivity(i,ito) = 1
	 endif
	
	 endif
	enddo

      return
	end


!  The following subrotine is not called by any other subrotines
 	subroutine CheckGenLinkOnConnectivity
! --  this subroutine check status of the generation link based on the 
! --  the connectivity of the downstream node
! --  i.e. is the downstream node doesnt' have any connectivity to all destinations
! --  remove it out from the generation link set.
	use muc_mod
	integer il

      do ito = 1, nzones
	do ilink = 1, NoofGenLinksPerZone(ito)
        do ip = 1, noof_master_destinations

         if(connectivity(idnod(LinkNoInZone(ito,ilink)),ip).gt.0) then
		il= LinkNoInZone(ito,ilink)
!		 call BacktrackPath(il,ip)
		endif

	  enddo
	enddo
	enddo


      do ito = 1, nzones
	do ilink = 1, NoofGenLinksPerZone(ito)
        do ip = 1, noof_master_destinations
         if(connectivity(idnod(LinkNoInZone(ito,ilink)),ip).gt.0) then
	        iflag1=1
		
	   endif 
	  enddo
	  if(iflag1.lt.1) then 


	  !if no generation loading factors are specified
		if (.not.LoadWeightID(ito)) then  !remove it from the generation link set

 	     do iPL = ilink+1, NoofGenLinksPerZone(ito)
             LinkNoInZone(ito,iPL-1)=LinkNoInZone(ito,iPL)
c --	print *,'Alex5',LinkNoInZone(ito,iPL-1)
	     enddo
	     NoofGenLinksPerZone(ito)=NoofGenLinksPerZone(ito)-1

	! write an error statement that 
	! ilink is not a valid generation link for zone ito

		else !if generation loading factors are specified
	!Do not delete the link as it will screw up the loading factors 
	!(the sum will be less than 1.0) 	
	
	write (911,*) 'Found invalid generation link in origin.dat file'
	write (911,*) 'The',ilink,'th Generation link in zone', ito
	write (911,*) 'is not connected to any destination in network'
	write (911,*) 'Remove link from generation set specified in'
	write (911,*) 'Origin.dat or check network connectivity'
	Stop
		endif
	endif	
	enddo
	enddo


      return
      end  





