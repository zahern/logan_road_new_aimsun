      subroutine build_mucpath_hov(mucindex)

      use muc_mod
      INTEGER testpath(1000)
      integer mucindex
	integer idtmp
	integer error
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
     
	if(mucindex.eq.1.and.iso_ok.eq.1) NumSoPath_hov(:,:,:) = 0
	if(mucindex.eq.1.and.iue_ok.eq.1) NumUePath_hov(:,:,:) = 0
	
c -- 
      do 100 j = 1,noof_master_destinations
c     write(9,*) 'Dest', j


!      do 200 i = 1,noofnodes
       do 200 i = 1,nzones
	testpath(:) = 0
	idtmp = 0
	

!      ifrom = i
      ifrom = origin(i)
      ito = j    
c  --
c  -- follow the shortest path code
c  --	
c           mov=backindex(icu1)-backpointr(ifrom)+1
c           mov=BackPointr(ifrom+1)-BackPointr(ifrom)+1


!            mov = 1 
           mov=BackPointr(ifrom+1)-BackPointr(ifrom)+1

c           know=labelpointerout(lt(j),ioc(j),ito,ifrom,ict,ibest,mov)
            know=labelpointerout(1,1,ito,ifrom,1,1,mov)
c --		           
            k=1
            testpath(k) = ifrom
            
c --
c --
      do 20 while(ifrom.ne.destination(ito))

!       if(connectivity(ifrom,ito).lt.1) then
c        print *, 'found poor connectivity for origin', ifrom
!        exit
!       endif

            idtmp = idtmp + ifrom
            ifromtmp=ifrom
            ktemp=know
            movetemp=mov
   	      icttemp = 1
	      testpath(k) = ifrom
            k = k + 1
            
	

         ict = 1
         mov=  pathpointerout3(1,1,ito,
     *                     ifromtmp,icttemp,ktemp,movetemp)
         know= pathpointerout2(1,1,ito,
     *                      ifromtmp,icttemp,ktemp,movetemp)
         ifrom=pathpointerout1(1,1,ito,
     *                      ifromtmp,icttemp,ktemp,movetemp)
c  -- There is one situation that will find no path
c  -- where no full connectivity from the origin to the destionation
         if(mov.lt.1.or.know.lt.1.or.ifrom.lt.1)then
          write(911,*) 'error in build muc path'
          write(911,*) 'for vehicle',j
          write(911,*) 'origin ',idnod(isec(j))
          write(911,*) 'destination ',destination(MasterDest(jdest(j)))
          exit
         endif 

20      continue

      testpath(k) = ifrom
      idtmp = idtmp + ifrom 
	iflag2 = 0


c --  check and remove cycle
      maxnu_pa = 1000
	if(kay .eq. 1) then
	nnk = k
	ifg2 = 0
455   continue
      do ml=3,nnk
       do kk=1,ml-1
       if(testpath(kk).eq.testpath(ml)) then
        ifg2 = 1
        idiff=ml-kk
        nnk=nnk-idiff
        do jd=kk,nnk
         testpath(jd)=testpath(jd+idiff)
        enddo
        do mm=nnk+1,maxnu_pa
         testpath(mm)=0
        enddo
        go to 455
       endif
       enddo
	enddo
c  -- update nodesum
      if(ifg2.gt.0) then
        idtmp= 0
        if(nnk.lt.1) print *, 'ueassign, nnk=',nnk
       do ii = 1, nnk
        idtmp = idtmp + testpath(ii)
       enddo
      endif
	endif
c  -- re-set k: number of nodes for this path testpath()
      k = nnk

! End of Modification

c --  if this is the first path for this OD
	IF(NumMucPath_hov(i,j).lt.1) then

	  NumMucPath_hov(i,j) = NumMucPath_hov(i,j) + 1

	  MucPathAtt_hov(i,j,NumMucPath_hov(i,j))%node_sum = idtmp
	  MucPathAtt_hov(i,j,NumMucPath_hov(i,j))%node_number = k
!	  traverse=>mucpath_hov(i,j,NumMucPath_hov(i,j))

c --  allocate this path in the link-list 
!	  ih = 1
!	  do while(testpath(ih).gt.0)
!         traverse%node = testpath(ih)
!         allocate(traverse%next_node)
!         traverse=>traverse%next_node
!	   ih = ih + 1
!	  enddo
!        nullify(traverse%next_node)


	ALLOCATE(MUCPath_Hov_Array(i,j,NumMucPath_hov(i,j))%P(k),
     +stat=error)
	if(error.ne.0) then
      write(911,*)"allocate P() in mucpath_hov_array vector, error"
	  pause
	endif
   
	! Copy contents from temp back to array 
	  ih = 1
	  do while(testpath(ih).gt.0)
	  MUCPath_Hov_Array(i,j,NumMucPath_hov(i,j))%P(ih) = testpath(ih)
        ih = ih + 1
	  enddo
        
	if(ih-1 .ne.k) then
	 print *, 'Inconsistency exists between the numbers of nodes
     +	  for MUC paths'
	pause
	endif



! End of Modification

c --  if this is not the first path, check with existing paths
c --  if this found to be new, add it 
        
        if(iso_ok.eq.1) then 
	   NumSoPath_hov(i,j,mucindex) = 1
	   call pathout_so_hov(i,j,NumMucPath_hov(i,j),
     +   mucindex,MucPathAtt_hov(i,j,NumMucPath_hov(i,j))%node_sum,
     +   MucPathAtt_hov(i,j,NumMucPath_hov(i,j))%node_number)
	  endif
	  if(iue_ok.eq.1) then
	   NumUePath_hov(i,j,mucindex) = 1
	   call pathout_ue_hov(i,j,NumMucPath_hov(i,j),
     +   mucindex,MucPathAtt_hov(i,j,NumMucPath_hov(i,j))%node_sum,
     +   MucPathAtt_hov(i,j,NumMucPath_hov(i,j))%node_number)
	  endif
  	ELSE

	 do icheck = 1, NumMucPath_hov(i,j)
	  if(idtmp.eq.MucPathAtt_hov(i,j,icheck)%node_sum) iflag2 = icheck
	 enddo
	 if(iflag2.eq.0) then  !new path found
	   NumMucPath_hov(i,j)=NumMucPath_hov(i,j) + 1


        if(NumMucPath_hov(i,j) .ge. muc_path_total_hov) then
!	    print *, 'origin:', i, '  destination:', j
	    call MUCArray_Reallocate(2) 
        endif
! End of modification

 	   MucPathAtt_hov(i,j,NumMucPath_hov(i,j))%node_sum = idtmp
	   MucPathAtt_hov(i,j,NumMucPath_hov(i,j))%node_number = k
!	   traverse=>mucpath_hov(i,j,NumMucPath_hov(i,j))
!	   ih = 1
!	   do while(testpath(ih).gt.0)
!           traverse%node = testpath(ih)
!           allocate(traverse%next_node)
!           traverse=>traverse%next_node
!	     ih = ih + 1
!	   enddo
!         nullify(traverse%next_node)


	ALLOCATE(MUCPath_Hov_Array(i,j,NumMucPath_hov(i,j))%P(k),
     +stat=error)
	if(error.ne.0) then
      write(911,*)"allocate P() in mucpath_hov_array vector, error"
	  pause
	endif
   
	! Copy contents from temp back to array 
	  ih = 1
	  do while(testpath(ih).gt.0)
	  MUCPath_Hov_Array(i,j,NumMucPath_hov(i,j))%P(ih) = testpath(ih)
        ih = ih + 1
	  enddo
        
	if(ih-1 .ne.k) then
	 print *, 'Inconsistency exists between the numbers of nodes
     +	  for MUC paths'
	pause
	endif



! End of Modification


        if(iso_ok.eq.1) then
	   NumSoPath_hov(i,j,mucindex)=NumSoPath_hov(i,j,mucindex)+1
	   call pathout_so_hov(i,j,NumMucPath_hov(i,j),
     +   mucindex,MucPathAtt_hov(i,j,NumMucPath_hov(i,j))%node_sum,
     +   MucPathAtt_hov(i,j,NumMucPath_hov(i,j))%node_number)
	  endif

	  if(iue_ok.eq.1) then
	   NumUePath_hov(i,j,mucindex)=NumUePath_hov(i,j,mucindex)+1
	   call pathout_ue_hov(i,j,NumMucPath_hov(i,j),
     +   mucindex,MucPathAtt_hov(i,j,NumMucPath_hov(i,j))%node_sum,
     +   MucPathAtt_hov(i,j,NumMucPath_hov(i,j))%node_number)
	  endif

	 else ! old path found

        if(iso_ok.eq.1) call pathout_so_hov(i,j,NumMucPath_hov(i,j),
     +   mucindex,MucPathAtt_hov(i,j,iflag2)%node_sum,
     +   MucPathAtt_hov(i,j,iflag2)%node_number)
	  if(iue_ok.eq.1) call pathout_ue_hov(i,j,NumMucPath_hov(i,j),
     +   mucindex,MucPathAtt_hov(i,j,iflag2)%node_sum,
     +   MucPathAtt_hov(i,j,iflag2)%node_number)        

	 endif
	
      ENDIF



1001	format(20i4)
c -------------------------------------------------------
      
200   continue

100   continue


      return
      end  





