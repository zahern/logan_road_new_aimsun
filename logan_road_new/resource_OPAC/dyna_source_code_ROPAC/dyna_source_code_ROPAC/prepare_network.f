         subroutine prepare_network()
c --
c -- This subroutine prepares all the required network data structures
c -- (i.e. forward star and backward star)
c --
c -- This suproutine is called from input.
c -- This subroutine does not call any other subroutines.
c --
c -- INPUT :
c --  Common block for the network data
c -- 
c -- OUTPUT :
c --  backward-star and forward-star representations of the network.
c --
      use muc_mod
c --
c -- The following block determines the number of connected
c -- downstream and upstream links for all the links in the network.
c -- Also, a list for these links is kept in inlink and llink
c -- respectively.
c -- Sept, 15,2001
c -- For Knoxville network, the movement.dat generated from TransCAD 
c -- has U turn always prevented.  It is because the two-way highway links 
c -- share the same node and U turn should be prevented on freeway,
c -- However, need to restore the U turn for surface streets

! --  llink, inlink contains U-turn
      
      do i=1,noofarcs


	     ixx=nu_mv+1 
		llink(i,ixx) = 0

        do j=1,noofarcs
          if(iunod(j).eq.idnod(i)) then
            llink(i,ixx)=llink(i,ixx)+1
		  
	 
            llink(i,llink(i,ixx))=j
            if(j.lt.i) topocont(i)=topocont(i)+1
		endif
        enddo
      enddo
c -- prepare the backward-star of the network, this will be used
c -- in the shortest path calculations (including penalty)
c --
	
      k=1
      do i=1,noofnodes
         backpointr(i)=k
        do j=1,noofarcs
          if(i.eq.idnod(j)) then
            UNodeOfBackLink(k)=iunod(j)
            BackToForLink(k)=j
            ForToBackLink(j)=k
            k=k+1
          endif
        enddo
        if((k-backpointr(i)+1).gt.MaxMove) then
	   MaxMove = k-backpointr(i)+1 !MaxMove is for KSP
		

	  endif
      enddo
      backpointr(noofnodes+1)=k

c --  prepare inlink based on backpointr

      do i = 1, noofarcs
      inlink(i,nu_mv+1) = backpointr(iunod(i)+1)-backpointr(iunod(i))
	  do j = 1, inlink(i,nu_mv+1)
          inlink(i,j) = BackToForLink(backpointr(iunod(i))+j-1)
	  enddo
	enddo

!	print *, 'previous value of MaxMove=',MaxMove


!      MaxMove = max(MaxMove+1,nu_mv) ! including one more movement for entry link
      MaxMove = nu_mv +1 ! including one more movement for entry link


52    format(20i4)
      return
      end
