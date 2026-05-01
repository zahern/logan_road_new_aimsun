      subroutine build_mucpath_lov(mucindex)

      use muc_mod
      INTEGER testpath(1000)
	real testpathlabel(1000)

      integer mucindex, idtmp, error, maxnu_pa
c --
c -- This subroutine builds the single muc path called mucpath()
c -- for the use in the muc procedure
c -- These paths are stored as Linked-List data structure to conserve memory
c -- mucpath(noofnodes,nzones,10) stores the initial 
c -- address for the linked-list so path
c -- traverse is the pointer for forwarding the linked-list
c --
c -- This subroutine is called from subroutine loop
c --
c -- This subroutine does not call any other subroutines.
c --
c -- INPUT
c -- None					  

c --
c -- OUTPUT	  
c -- mucpath 
!	print *, 'before build_mucpath_lov iteration =  ',iteration
!	pause

      kkki=nodenum(1)

	if(mucindex.eq.1.and.iso_ok.eq.1) NumSoPath_lov(:,:,:)=0
	if(mucindex.eq.1.and.iue_ok.eq.1) NumUePath_lov(:,:,:)=0
c -- 
      do 100 j=1,noof_master_destinations

!      do 200 i = 1,noofnodes
      do 200 i=1,nzones

C	print *, 'Alex931'

	if(i.eq.3.and.j.eq.10) iiidebug=1
	 
	testpath(:)=0
	idtmp=0

!     ifrom = i
      	ifrom=origin(i)
      	ito=j

!            mov = 1 
           mov=BackPointr(ifrom+1)-BackPointr(ifrom)+1
           know=labelpointerout(1,1,ito,ifrom,1,1,mov)
           k=1
           testpath(k)=ifrom
c --
C	print *, 'Alex932'

      do 20 while(ifrom.ne.destination(ito))

!       if(connectivity(ifrom,ito).lt.1) then
!        exit
!      endif

          idtmp=idtmp+ifrom
          ifromtmp=ifrom
          ktemp=know
          movetemp=mov
   		icttemp=1
		testpath(k)=ifrom
          k=k+1
          ict=1
         mov=pathpointerout3(1,1,ito,
     *                     ifromtmp,icttemp,ktemp,movetemp)
         know=pathpointerout2(1,1,ito,
     *                      ifromtmp,icttemp,ktemp,movetemp)
         ifrom=pathpointerout1(1,1,ito,
     *                      ifromtmp,icttemp,ktemp,movetemp)
c  -- There is one situation that will find no path
c  -- where no full connectivity from the origin to the destionation
	testpathlabel(k)=Label(ifromtmp,icttemp,ktemp,movetemp)

         if(mov.lt.1.or.know.lt.1.or.ifrom.lt.1)then
           write(911,*) 'error in build muc path'
           write(911,*) 'for vehicle',j
           write(911,*) 'origin ',idnod(isec(j))
           write(911,*) 'destination ',destination(MasterDest(jdest(j)))
           exit
         endif 

20      continue
C	print *, 'Alex933'						! critical
      testpath(k)=ifrom
      idtmp=idtmp+ifrom 
	iflag2=0

C	print *, 'Alex9331',i,j						! critical
C	print *, 'Alex9331',NumMucPath_lov(i,j)	
c --  if this is the first path for this OD
	IF(NumMucPath_lov(i,j).lt.1)then
C	  print *, 'Alex9332'						! critical
	  NumMucPath_lov(i,j)=NumMucPath_lov(i,j)+1
	  MucPathAtt_lov(i,j,NumMucPath_lov(i,j))%node_sum=idtmp
	  MucPathAtt_lov(i,j,NumMucPath_lov(i,j))%node_number=k
c	  traverse=>mucpath_lov(i,j,NumMucPath_lov(i,j))
	  ALLOCATE(MUCPath_Lov_Array(i,j,NumMucPath_lov(i,j))%P(k),
     +    stat=error)
		if(error.ne.0)then
          write(911,*)"allocate P() in mucpath_lov_array, error"
		pause
		endif
C	  print *, 'Alex9334'						! critical   
	! Copy contents from temp back to array 
	  ih=1
	  do while(testpath(ih).gt.0)
	  MUCPath_Lov_Array(i,j,NumMucPath_lov(i,j))%P(ih)=testpath(ih)
          ih=ih+1
	  enddo
C	  print *, 'Alex9335'        					! critical
		if(ih-1.ne.k)then
	  print *, 'Inconsistency exists between the numbers of nodes
     +	  for MUC paths'
		pause
		endif
! End of Modification

C	print *, 'Alex934'						! critical

c --  if this is not the first path, check with existing paths
c --  if this found to be new, add it 
        
		if(iso_ok.eq.1)then 
	 NumSoPath_lov(i,j,mucindex)=1
	 call pathout_so_lov(i,j,NumMucPath_lov(i,j),
     +   mucindex,MucPathAtt_lov(i,j,NumMucPath_lov(i,j))%node_sum,
     +   MucPathAtt_lov(i,j,NumMucPath_lov(i,j))%node_number)
		endif

		if(iue_ok.eq.1)then
	 NumUePath_lov(i,j,mucindex)=1
	 call pathout_ue_lov(i,j,NumMucPath_Lov(i,j),
     +   mucindex,MucPathAtt_lov(i,j,NumMucPath_Lov(i,j))%node_sum,
     +   MucPathAtt_Lov(i,j,NumMucPath_Lov(i,j))%node_number)
		endif

  	ELSE
c	print *, 'Alex9341'
		do icheck=1,NumMucPath_lov(i,j)
	  if(idtmp.eq.MucPathAtt_lov(i,j,icheck)%node_sum) iflag2=icheck
		enddo
c	print *, 'Alex9342',iflag2
		if(iflag2.eq.0)then  !new path found

			NumMucPath_lov(i,j)=NumMucPath_lov(i,j)+1

			if(NumMucPath_lov(i,j).ge.muc_path_total_lov)then
!	    print *, 'origin:', i, '  destination:', j
c	print *, 'Alex9343'
				call MUCArray_Reallocate(1) 
			endif
! End of modification

c	print *, 'Alex935'

 		MucPathAtt_lov(i,j,NumMucPath_lov(i,j))%node_sum=idtmp
		MucPathAtt_lov(i,j,NumMucPath_lov(i,j))%node_number=k

	ALLOCATE(MUCPath_Lov_Array(i,j,NumMucPath_lov(i,j))%P(k),
     +stat=error)
	if(error.ne.0) then
      write(911,*)"allocate P() in mucpath_lov_array vector, error"
	  pause
	endif
   
	! Copy contents from temp back to array 
		ih=1
		do while(testpath(ih).gt.0)
	  MUCPath_Lov_Array(i,j,NumMucPath_lov(i,j))%P(ih)=testpath(ih)
          ih=ih+1
		enddo
        
		if(ih-1.ne.k) then
	 print *, 'Inconsistency exists between the numbers of nodes
     +	  for MUC paths'
	pause
		endif
! End of Modification

		if(iso_ok.eq.1)then
	   NumSoPath_lov(i,j,mucindex)=NumSoPath_lov(i,j,mucindex)+1
	   call pathout_so_lov(i,j,NumMucPath_lov(i,j),
     +   mucindex,MucPathAtt_lov(i,j,NumMucPath_lov(i,j))%node_sum,
     +   MucPathAtt_lov(i,j,NumMucPath_Lov(i,j))%node_number)
		endif
		if(iue_ok.eq.1)then
	   NumUePath_lov(i,j,mucindex)=NumUePath_lov(i,j,mucindex)+1
	   call pathout_ue_lov(i,j,NumMucPath_Lov(i,j),
     +   mucindex,MucPathAtt_Lov(i,j,NumMucPath_Lov(i,j))%node_sum,
     +   MucPathAtt_Lov(i,j,NumMucPath_Lov(i,j))%node_number)
     
		endif
		else ! old path found
		if(iso_ok.eq.1) call pathout_so_lov(i,j,NumMucPath_lov(i,j),
     +   mucindex,MucPathAtt_lov(i,j,iflag2)%node_sum,
     +   MucPathAtt_lov(i,j,iflag2)%node_number)
		if(iue_ok.eq.1) call pathout_ue_lov(i,j,NumMucPath_lov(i,j),
     +   mucindex,MucPathAtt_lov(i,j,iflag2)%node_sum,
     +   MucPathAtt_lov(i,j,iflag2)%node_number)        

	 endif
	
      ENDIF
c	print *, 'Alex936'

1001	format(20i4)
     
200   continue

C	print *, 'Alex937'

100   continue
C	print *, 'Alex938'

!	print *, 'after build_mucpath_lov iteration =  ',iteration
!	pause

      return
      end  
